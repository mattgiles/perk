# perk Roadmap

A Pi-native rebuild of the erk plan-oriented engineering workflow, sequenced so that
**perk bootstraps itself**: each phase leaves perk capable of driving the next.

See [RESEARCH.md](./RESEARCH.md) for the full problem analysis and the Pi-native
architecture rationale this roadmap is built on, [cli-vs-pi.md](./cli-vs-pi.md) for the
CLI/extension split, and the two Pi pattern studies the phases below lean on:
[pi--best-practices.md](./pi--best-practices.md) (the **authoritative** patterns from Pi's
own `examples/`, including the SDK) and
[agent-stuff-best-practices.md](./agent-stuff-best-practices.md) (idiomatic real-world
patterns from `mitsuhiko/agent-stuff`).

## Core thesis

Port **the workflow, not the binary**. erk's durable value is its loop
(**plan → save → implement → ship**), wrapped by **objectives** (multi-plan
coordination) and **PR review / CI iteration**. Rebuild that in Pi by putting each
behavior in the right primitive:

- **Skills** — portable "how to do this well" knowledge (objective framing, PR review
  etiquette, CI iteration, coding standards).
- **Extensions** — the control plane: deterministic commands, tool gating, mode state,
  GitHub mutations. Anything that mutates state, touches GitHub, changes modes, or must
  happen consistently lives here, never in a passively-triggered skill.
- **GitHub** — canonical durable storage (objectives, plans, PR state).
- **Pi session entries** (`appendEntry`) — transient workflow state (current mode,
  active objective/plan, checkpoints, last review batch).

**Hard rule:** every workflow boundary is an explicit command or tool. Pi may not
auto-load a full `SKILL.md`, so critical transitions must never depend on passive skill
triggering.

## Context strategy: three tiers (cross-cutting)

This is the empirical backbone of the thesis above (PRIOR_ART §6). Agent evals show
skills-by-default perform *identically to having no docs* (the "retrieval paradox": an
agent won't invoke a skill it doesn't know it needs), while a compressed index in
`AGENTS.md` reaches ~100% compliance. So perk injects knowledge at three tiers, and every
reminder lives at **exactly one** — the most specific tier that achieves compliance:

1. **Ambient** → `AGENTS.md` + Pi context files. A **compressed index of what exists**, not
   walls of prose. Always present; for universal rules and awareness.
2. **Per-prompt** → `before_agent_start` system-prompt injection / the `input` event. For
   session-wide routing and dynamic state (active plan/objective, mode, branch). When the
   `input` event does just-in-time work (e.g. injecting a diff), **skip it during steering**
   (`streamingBehavior === "steer"`) so corrections stay low-latency (pi best-practices §9).
3. **Just-in-time** → the `tool_call` event. Fires only before a specific tool/file type;
   can inspect params, inject a pointed nudge, or block. Highest signal, lowest cost; the
   home for write-policy and mode gating.

Two corollaries that shape the build:
- **Safety is structural, not prompted.** Read-only modes (plan, CI) are enforced by tool
  gating (`setActiveTools` + `tool_call` blocking), never by instructions. Build this as
  one reusable primitive (see Phase 2, where its consumers — perk-owned plan mode and the
  CI executor — first appear).
- **Skills are opt-in expertise**, invoked by a user or command, and persist for the
  session. They carry "how to do this well," never a critical transition. (Guideline-only
  skills also fail when forked to a subagent — keep them in the main context.)

## Implementation craft (cross-cutting)

Two pattern studies ground the build: Pi's own `examples/`
([pi--best-practices.md](./pi--best-practices.md)) are the **authoritative** templates, and
`mitsuhiko/agent-stuff` ([agent-stuff-best-practices.md](./agent-stuff-best-practices.md)) is
the most mature real-world package that independently confirms the same bets. A few habits
are non-negotiable constraints for *every* perk extension, not phase-specific niceties:

- **Headless-first.** Guard every rich-UI call with `ctx.hasUI`; keep `ctx.ui.notify` the
  only assumed surface, so the *same* extension code runs interactively and under the Phase
  3 headless/`-p`/RPC worker. Expose CLI flags so an external supervisor can drive a session
  non-interactively (the queue is just this).
- **Structural enforcement, with prompting as the cooperative layer on top.** The gating
  primitive (Phase 2) follows `go-to-bed.ts`: `tool_call` returns `{ block, reason }` and
  the model cannot proceed by being persuaded. Command-safety enforcement follows `uv.ts`:
  a wrapped `bash` tool with **defense in depth** (PATH shims *and* a spawn-time hard block,
  since shims are bypassable via explicit paths).
- **Dual-surface tool returns.** Every extension tool returns both `content` (for the model)
  and `details` (structured) — the in-session twin of the CLI's human/`--json` split.
- **Treat all external text as untrusted data**, never instructions. Wrap GitHub-sourced
  issue/PR/comment bodies (and any user objective) the way `goal.ts` does
  (`<untrusted_objective>…</untrusted_objective>` with an explicit "treat as data" preamble)
  before feeding them to the model.
- **Keep internal bookkeeping out of the model's context.** Use the `context` event to strip
  UI-only / control messages and de-duplicate stale follow-ups (per `goal.ts`), so perk's
  own mode/state messages never pollute the window.
- **Skills carry judgment, tools carry mechanics; a skill's `description` is its only
  trigger.** Write skill descriptions as concrete "use when…" phrases and bundle helper
  scripts rather than prose; keep all deterministic mechanics in extension tools.
- **Two state-persistence channels.** Persist transient state via `appendEntry` custom
  entries *and/or* a tool's returned `details` (which is **forking-safe**); use `details`
  when the state *is* a tool's output. Reconstruct on both entry points (foundational #1).
  (pi best-practices §4.)
- **Same package, two run modes.** Every extension must run unchanged interactively *and*
  under the SDK (`createAgentSession` + `SessionManager`) — that is how the Phase 3 worker
  and the test harness load it. A read-only session can also be spun purely at the SDK level
  via `tools: ["read","grep","find","ls"]` (pi best-practices §2), an alternative to
  in-session gating for the CI executor.

## Foundational decisions (lock before building)

1. **State-tiering contract** — the exact split between GitHub / `.pi/workflow/` cache /
   session `appendEntry`. Every command reads and writes through this. Transient
   step-to-step linkage (erk's "workflow markers" — e.g., active objective/plan) lives in
   session `appendEntry` custom entries, **rebuilt from the session on both `session_start`
   and `session_tree`** (branch navigation also changes the current branch — the working
   discipline from agent-stuff's `goal.ts`/`loop.ts`, and the live antidote to stale
   markers). **Lesson from erk
   (PRIOR_ART §8):** the objective↔plan link was a marker that *failed silently* when not
   set at the right moment — make such linkage explicit and **verified** (read it back and
   check), never fire-and-forget. **Design property
   to preserve:** the durable workflow state must be reconstructable from GitHub-native
   artifacts alone (labels, comments, PR draft status). That property is what makes the
   workflow resumable, debuggable, and — critically — queue-able by the Phase 3 headless
   worker. The `.pi/workflow/` cache and session entries are accelerators, never the only
   copy of truth. (See PRIOR_ART §1.)
2. **Plan storage model** — draft-PR-backed plans (erk-legacy, migration-friendly) *or*
   the simpler "single canonical body + workflow-created PR" direction. Shapes the whole
   GitHub layer. **Lean (PRIOR_ART §12):** adopt erk's *newer* simplification (single
   canonical body + workflow-created PR) rather than reproducing the legacy draft-PR
   plumbing — keep migration-compat as a Phase 3 import helper, not a v1 constraint. Includes
   the **lifecycle state machine**: a minimal, machine-readable `lifecycle_stage` (erk's
   durable set collapses to roughly `planned → impl`, with `merged`/`closed` inferred from PR
   state, not stored). Start with the fewest stages that are *observably distinct from GitHub
   state*; erk's lesson was that it over-split stages and later had to consolidate them. (See
   PRIOR_ART §1.) Whichever direction is chosen, adopt erk's proven **storage discipline**
   (PRIOR_ART §2): a **two-part split** — compact, queryable metadata (header) separate from
   the full plan body (collapsible, fetched only when needed) — and a **provider-agnostic plan
   ref** as the *sole* source of truth for plan↔branch mapping (string ID + `provider` field, so
   non-GitHub backends stay cheap; never encode state in branch names). Saves must be
   **idempotent** keyed on the Pi session id (prevents retry-loop duplicate plans), and
   commands must tolerate **staged field population** (branch/PR refs are null until
   submit) via LBYL checks.
3. **Stage registry** — the single declarative, language-neutral schema that enumerates the
   workflow's resumable **stages** and, per stage, a descriptor: the worktree/branch it
   needs, the state it reads/writes, the extension command it maps to, its legal
   predecessors/successors, and which **entry doors** are allowed (warm in-session,
   cold-local, cold-remote). The Python `perk` CLI generates its subcommands from this
   registry; the TS extension drives its in-session transitions from it — so CLI↔extension
   parity is **by construction, not discipline** ([cli-vs-pi.md](./cli-vs-pi.md) §4). Lock
   the stage set and descriptor shape *before building*, because both planes depend on it
   and it is the contract that keeps the two languages from drifting. Start with the
   smallest set that closes the loop (`plan → save → implement → ship`); add
   `objective-plan`, `submit`/`address`/`land`, and `learn` as Phase 2 deepens.
4. **GitHub access strategy** — shell out to `gh` first (matches existing auth
   assumptions), then harden metadata-sensitive operations behind deterministic extension
   tools. Decide the *seam* now even if v1 is shell-based.
5. **Command naming** — flat (`/plan`, `/implement`, `/ship`) vs hyphenated
   (`/perk-*`). Low-stakes; decide quickly.

## The bootstrap arc

Two organizing principles. **Borrow-then-own:** compose existing Pi gallery packages to get
a working loop immediately, then progressively internalize each piece into perk-owned,
GitHub-backed, deterministic surfaces. **Close-then-deepen:** close a *thin* end-to-end loop
first so perk can ship perk, then deepen each stage *through that loop* — deferring the most
speculative work (objectives) until a real plan→ship pipeline exists to validate it.

```
Phase 0:  skeleton + CLI(init/doctor/worktree) + borrowed plan mode   →  can PLAN perk
Phase 1:  close the thin loop  (plan → save → implement → ship)       →  perk SHIPS perk
Phase 2:  deepen the loop  (objectives, CI iteration, review, recon)  →  perk ships perk WELL
Phase 3:  headless worker, queue, migration, tests                    →  perk's backlog runs itself
```

Each arrow is a **dogfood gate**: a phase does not start until the previous one made perk
able to drive it. The close-then-deepen ordering makes the gates *stronger* — because the
whole loop closes at the end of Phase 1, every later stage is built *through perk's own
plan→ship loop*, not merely through planning.

## Phases

### Phase 0 — Skeleton + dogfood substrate (borrow)

Stand up the distributable Pi package (`package.json`, `extensions/`, `skills/`,
`prompts/`) and a project-local `.pi/settings.json` that loads it. Follow agent-stuff's
packaging idiom (best-practices §2): glob resource directories with `!` negation for opt-in
pieces, declare the Pi APIs (`@earendil-works/pi-coding-agent`, `pi-ai`, `pi-tui`,
`typebox`) as `peerDependencies`, and tag the documented `pi-package` / `pi-extension` /
`pi-skill` keywords. Implement the
state-tiering contract and `.pi/workflow/` layout (materialized plan cache + a
session-scoped scratch area for inter-process workflow files, the analogue of erk's
`.erk/scratch/sessions/<id>/`) as real read/write helpers with no
workflow logic yet — prove a command can persist session state via `appendEntry`,
restore it on reload, and read/write the local cache. Establish `AGENTS.md` (as a
**compressed index**, per the context strategy above) and project conventions so
perk-developing-perk is coherent.

Then adopt the curated default set as **borrowed scaffolding**:

- `@tombell/pi-plan` — instant read-only planning mode (`/plan`, `Ctrl+Alt+P`, `--plan`).
- `@juicesharp/rpiv-todo` — checklist overlay surviving `/reload` and compaction.
- `@tombell/pi-diff` + a status bar (`@tombell/pi-status` or `pi-powerline-footer`).

**CLI slice.** Stand up the **`perk` CLI exterior** (the session host — see
[cli-vs-pi.md](./cli-vs-pi.md)): `init`, `doctor`, **worktree lifecycle** (create / list /
remove), a **process-launch primitive** (exec `pi`, primed for a stage), and the
**stage-registry plumbing** that turns foundational decision #3 into generated subcommands.
`init`/`doctor` are perk-native ports of erk's commands (see
[erk source](https://github.com/dagster-io/erk): `src/erk/cli/commands/init/main.py`,
`src/erk/cli/commands/doctor.py`) and are CLI commands, not slash commands — they are part of
the substrate, not a later nicety: `init` is what makes a repo dogfoodable, and `doctor` is
what keeps the borrowed-package + GitHub setup trustworthy while everything else is in flux.
The per-stage **cold-door launchers** (`perk plan`, `perk implement`, …) arrive with their
stages in Phases 1–2; Phase 0 builds the plumbing they plug into.

**`perk init`** — port erk's idempotent, multi-step init. The bootstrap order is
shell-first: install the `perk` CLI (`pip`/`uv`), then `perk init` runs *from the shell* to
scaffold the repo, including `pi install -l` of the perk extension package (writing
`.pi/settings.json`). The agent can't bootstrap itself, so this is exterior by nature.
Carry over these behaviors from erk:

- **Verify environment** — git repo present, `gh`/git/node available, GitHub auth
  (erk Step 1 + prerequisite checks).
- **Scaffold config + state** — the three-tier layout from the foundational decisions:
  shared project config, per-user-local (gitignored) config, and the `.pi/workflow/`
  cache. Mirrors erk's `.erk/config.toml` / `config.local.toml` split.
- **Install/verify the borrowed default packages** and write the recommended set into
  `.pi/settings.json` (the perk analogue of erk's "artifact sync" + capability install).
  Track *which* optional perk pieces and borrowed packages are enabled, and distinguish
  **required** (auto-installed, always present) from **optional** (opt-in) — mirrors erk's
  capability model (PRIOR_ART §9).
- **Manage `.gitignore`** for transient state (`.pi/workflow/` scratch, local config).
- **Set up GitHub** — ensure perk's labels/state scaffolding exist (erk's PR-repo label
  setup), gated on the plan-storage-model decision.
- **Idempotent + `--upgrade`/`--force`/`--no-interactive`** — detect already-initialized
  repos, preserve user config on upgrade, re-sync managed pieces.
- **Post-init handoff** — port erk's post-init prompt hook: hand the agent a markdown
  file to execute. This is the literal hand-off point where perk starts dogfooding
  itself.

**`perk doctor`** — port erk's grouped health checks with structured results
(`passed` / `warning` / `info` / `message` / `details` / `remediation`), condensed-vs-
`--verbose` output, and consolidated remediation. Adapt the check set to Pi:

- **Environment / User Setup** — pi version, `gh`/git/node present, GitHub auth.
- **Package Setup** — perk package loaded, borrowed/recommended packages installed and
  at expected versions, `.pi/settings.json` wiring intact.
- **Repository Setup** — `.pi/workflow/` integrity, config present and valid, `.gitignore`
  entries, GitHub labels/state scaffolding.
- **State consistency** — session `appendEntry` state coherent with the local cache and
  GitHub (the state-tiering contract's self-check).
- **Check only what's enabled** (PRIOR_ART §9): required pieces are always checked; optional
  pieces/packages only when enabled. Support a **self-vs-consumer dual mode** — in perk's
  own repo, check everything (dogfooding); in a consumer repo, check only the enabled set.
- **`--fix`** — apply known remediations automatically (mirrors erk's `doctor --fix`).
- Defer erk's `doctor workflow` GitHub-CI smoke test to **Phase 3** (it needs the headless
  worker and queue to exist).

**Dogfood gate:** from here on, every subsequent phase is planned in read-only plan mode
with a live todo overlay, on a repo that `perk init` scaffolded and `perk doctor` keeps
healthy. perk's earliest self-use is *planning perk*.

### Phase 1 — Close the thin loop (own the spine)

Goal: a *minimal* end-to-end **plan → save → implement → ship** that lets **perk ship
perk**. Build only the spine; defer every deepening (objectives, CI iteration, review
classification, the PR-body craft) to Phase 2. The point is to close the loop fast so that
all later depth is built *through* it.

Keep **borrowed plan mode** for read-only exploration — don't internalize it yet, since that
needs the gating primitive, which lands in Phase 2 alongside its consumers (perk-owned plan
mode and the CI executor). Build perk-owned, GitHub-backed **plan storage** and the spine
commands on top of it:

- **`/plan-save`** — the storage mechanics from foundational decision #2 (PRIOR_ART §2):
  header/body split on the GitHub side, a provider-agnostic **plan ref** materialized in
  `.pi/workflow/` with the canonical copy in GitHub and transient linkage in session
  `appendEntry`, **idempotent** on the Pi session id. Make it a **terminating tool**
  (`terminate: true`) so the turn ends on the save without an extra LLM round-trip, and mark
  cache-mutating tools `executionMode: "sequential"` to avoid races on the `.pi/workflow/`
  cache (pi best-practices §6). Encode the **plan-authoring rules** in the planning skill —
  most importantly erk's hard rule that **line-number references are disallowed** (they
  drift); require durable anchors (function names, behavioral descriptions, structural
  locations) instead.
- **`/implement`** — a *thin* execution path. The primary transition is the **CLI cold
  door** (`perk implement <plan>`: materialize the worktree from the plan ref + launch a
  fresh `pi`), which gives a clean implement context *for free* — no perk-owned gating or
  `handoff` sophistication required yet. The warm in-session command just continues in the
  current worktree.
- **`/ship`** — a *thin* finish: commit, open a PR whose body carries the plan, and land it
  once approved. Defer the two-target body craft, `pr check`, and the draft→ready nuance to
  Phase 2.

**Stage-transition hygiene.** Guard the spine's transitions with Pi's **session-lifecycle
gates** (`session_before_switch` / `session_before_fork` → `{ cancel }`): port erk's
dirty-repo / commit-before-leaving checks, failing safe (block) when headless (pi
best-practices §7).

**CLI slice:** the cold-door launchers for the spine — `perk plan`, `perk implement`,
`perk ship`, and `perk resume <plan>` — generated from the stage registry (foundational #3).

**Testing starts here, not in Phase 3.** A self-hosting tool must test its deterministic
core (plan storage, plan-ref, the registry) as it is built. Stand up command/extension tests
via the SDK + `SessionManager.inMemory()` (pi best-practices §2) from this phase on; only the
end-to-end *worker* tests wait for Phase 3.

**Dogfood gate:** perk ships perk. Every Phase 2 and Phase 3 change is authored and saved as
a perk plan, then implemented and landed *through perk's own thin loop* — so all later
deepening rests on a validated plan→ship spine, not on planning alone.

### Phase 2 — Deepen the loop (objectives, CI, review)

With the thin loop closed, deepen each stage *through perk's own plan→ship loop* — the true
dogfooding the close-then-deepen ordering buys. This is where the differentiating depth
lands: **objectives** (the plan factory), the **read-only CI executor**, **review
handling**, and the polished PR mechanics. Port `pr-operations` and CI-iteration skills.
Project-local markdown (the old `.erk/prompt-hooks/*`) becomes extension-injected config at
the right workflow point (via `before_agent_start` or the `resources_discover` event — pi
best-practices §12).

**Build the tool-gating primitive here** (its consumers now exist): a read-only allowlist
via `setActiveTools` + blocking unsafe calls in `tool_call`, designed once and generically
so the *same* machinery powers perk-owned plan mode *and* the read-only CI executor
(PRIOR_ART §5). Pi's own `examples/plan-mode/` is the **complete authoritative recipe** (pi
best-practices §5): `setActiveTools` allowlist + `tool_call` bash sub-allowlist + hidden
`before_agent_start` mode-context + `context` strip-when-off + persist/restore + a `--plan`
flag; and `examples/preset.ts` generalizes it (model + thinking + tools + instructions, with
**snapshot-then-restore** and project-overrides-global config) — its shipped config literally
defines `plan`/`implement` presets, so perk's mode system is an already-blessed pattern.
(agent-stuff's `go-to-bed.ts` is the template for the `{ block, reason }` half.) With the
primitive in hand, **decide whether to internalize `@tombell/pi-plan` or keep wrapping it** —
an evidence-based call after a full loop of use — and tie perk-owned plan mode to `/plan-save`
+ GitHub state. Deepen `/implement`'s warm path with the `ctx.newSession` / handoff pattern
for a fresh context (pi best-practices §8), the in-process twin of the CLI cold door.

**Objectives as plan factories** (PRIOR_ART §3). Now that the loop is closed and validated,
add the objective layer: treat an objective as a long-running goal that *generates bounded
plans*, not something implemented directly — the genuine differentiator over simpler gallery
workflows, and the reason it lands *after* a working plan→ship pipeline exists to prove the
plans it emits are useful. Carry over erk's storage model: frontmatter is canonical, a
rendered table is for humans, steps are a **flat list with phases derived from ID prefix**.
Split responsibilities the same way as plans: the **mechanics** (storage, step mutation,
status, dependency-graph next-node selection for `/objective-plan`) are deterministic
extension tools; the **judgment** (which node to plan, which nodes a PR completed) stays in
skills/prompts.

Borrow directly from agent-stuff's `goal.ts` (best-practices §11), the closest working prior
art to a long-running objective: **budget accounting** (sum assistant token usage on
`agent_end`, track elapsed wall-time, surface it in a status line) and — most valuable — a
**completion-audit contract** for "are we done?": before marking an objective node complete,
the model must build a prompt-to-artifact checklist mapping every explicit requirement to
real evidence, and *treat uncertainty as not-done*. Expose objective transitions as model
tools whose descriptions strictly bound when they may fire ("only when explicitly
requested," "only when actually achieved"), not as free-form prose the model interprets.
For long-running loops, keep within the context window with threshold-triggered compaction
(`ctx.getContextUsage` + `ctx.compact`, or a custom `session_before_compact` summary on a
cheaper model — pi best-practices §9).

**Deepen PR submission** — split the thin `/ship` into `/pr-submit` + land, and carry over
(PRIOR_ART §4):
- **Feed plan context into PR generation** so the description matches original intent, and
  use the **two-target split** — a plain-text commit message vs an HTML-enhanced GitHub PR
  body that embeds the full plan in a collapsible section (plan in the PR, not the commit).
- Provide a **`pr check` validation step** (e.g., a plain-backtick checkout footer, not
  HTML `<details>`, so validation is stable).
- Use **draft → ready-for-review as the deliberate review gate**; never infer completion
  from PR open/closed state alone — diff for changes outside the plan files.

**Review handling & CI iteration** — the highest-value patterns to port (PRIOR_ART §5):
- **Read-only CI executor**: run CI in a tool-gated context with no `edit`/`write`, using
  the **Run → Report → Fix → Verify** cycle — the executor reports failures, the parent
  agent analyzes and fixes, the executor re-verifies. This structurally prevents the
  "auto-fix trap" (blind `--fix`, broad excepts, suppressed warnings) and keeps noisy test
  output out of the main context. Uses the gating primitive built above. agent-stuff supplies
  two working templates (best-practices §9, §11): `loop.ts`'s
  iterate-until-`signal_success` controller for the cycle, and `review.ts`'s `navigateTree`
  branch-and-return sub-session (run the read-only pass in a child branch against a rubric,
  then inject only the summary) to keep the noisy work out of the main context window. The
  **authoritative** isolated-context template is Pi's own `examples/subagent/`
  (pi best-practices §8): spawn `pi --mode json -p --no-session --tools <read-only set>`,
  stream/parse JSON events, propagate abort, and **cap model-visible output while keeping
  the full result in `details`** — or, equivalently, spin a read-only SDK session
  (`tools: ["read",…]`). Project-supplied agents/prompts are untrusted: gate them behind a
  scope flag + confirm.
- **`/pr-address` = classify-then-act**: classify each piece of feedback
  (actionable / informational / praise / question) *before* acting; only actionable items
  get code changes. Offer a **preview variant** (classification only). Distinguish **review
  threads vs discussion comments** (different GitHub APIs, counted separately).
- **Batched, schema'd thread resolution**: resolve addressed threads in one deterministic
  operation with a strict schema (`[{thread_id, comment}]`), not one-by-one.
- **Plan File Mode**: when a PR's diff is just the plan file, `/pr-address` reinterprets
  feedback as "edit the plan text," not "implement it."
- Keep classification *judgment* in a skill/prompt; keep resolution/fetch *mechanics* in
  deterministic extension tools.
- **Deterministic post-edit formatting** via `tool_result` middleware (PRIOR_ART §7): the
  Pi analogue of erk's PostToolUse Ruff-on-edit — run the project formatter automatically
  after `edit`/`write`, so formatting never becomes a CI iteration. This is the
  middleware-style use of `tool_result` (distinct from the `tool_call` gating primitive).

Include **objective reconciliation after landing** (PRIOR_ART §3): when a PR linked to an
objective node merges, mark the node done (mechanical, deterministic) and have the model
reconcile stale objective prose against what was *actually* built — "the roadmap is a
source of truth for what exists, not just what was intended." erk separates body sections
into Mechanical (command-updated), Reconcilable (LLM-updated post-merge), and Immutable
(never touched); mirror that boundary so reconciliation never clobbers historical notes.

**CLI slice:** cold doors for the deepened stages — `perk objective-plan`, `perk submit`,
`perk address`, `perk land` — plus the **local-vs-remote target** option on each
([cli-vs-pi.md](./cli-vs-pi.md) §4.5), the seam the Phase 3 worker reuses.

**Dogfood gate:** perk now drives its *full* workflow on itself — objectives select the next
plan, the read-only CI executor iterates, reviews are classified and resolved, and objective
prose reconciles after landing. `rpiv-todo` checklists can be retired in favor of perk-owned
checkpoints; the borrow→own internalization is largely complete.

### Phase 3 — Headless worker, queue, migration, tests (own autonomy)

Build a headless runner on the Pi **SDK** — `createAgentSession` with a `SessionManager`
(`continueRecent` / `open` to resume by file), a **locked-down `resourceLoader`** (run a
fixed resource set in CI without touching the user's config), and **settings overrides**
(`compaction` / `retry` off) for deterministic runs (pi best-practices §2) — or drive a
child `pi --mode json -p` as the `examples/subagent/` template does (pi best-practices §8).
Either way it runs the *same package* the local user runs and streams structured events
back into GitHub comments/checks. This works only because every extension was built
headless-first (the `ctx.hasUI` discipline above). When the worker **replaces** the active
session (resume/fork/import), follow the `createAgentSessionRuntime` rebind rule —
re-`subscribe` and `bindExtensions` to the new session (pi best-practices §2). agent-stuff's
`control.ts` (startup flags as a non-interactive drive API) and `split-fork.ts` (fork a
session file + spawn a fresh `pi`) are corroborating patterns. Add migration helpers
(import existing planned PRs, translate objective markers, map residual `.claude`
references). **Extend the test suite** from Phase 1's command/extension tests (SDK +
`SessionManager.inMemory()`) to **end-to-end worker tests** via RPC/JSON mode. Developed
entirely through perk's interactive loop.

**CLI slice:** the supervisor — queue management and `workflow run` list / cancel / retry
([cli-vs-pi.md](./cli-vs-pi.md) §2.2), launching stages on the **remote** target. This is
the Phase 2 cold doors run by a process instead of a human.

**Dogfood gate:** perk schedules and executes its own remaining work.

## Default packages: bootstrap set vs permanent set

"What to install by default" has two layers and two mechanisms:

- **Mechanisms:** bundled dependency of the perk package (`dependencies` +
  `bundledDependencies`) for anything the workflow relies on; **recommended set** written
  into the scaffolded `.pi/settings.json` for additive, swappable UX. agent-stuff proves a
  third mechanism (best-practices §2): thin **distribution sub-packages** (`mitsupi-common`
  vs `mitsupi-loaded`) that re-list curated subsets, plus **opt-in-by-packaging** via `!`
  glob negation — the model for perk's permanent recommended set vs. a heavier/optional
  add-on bundle.
- **Layers:** a **temporary bootstrap set** (lets perk exist before perk is built) and a
  **permanent recommended set** (additive UX perk never bothers to own).

### Internalization schedule

| Borrowed in Phase 0 | Internalized | Why |
|---|---|---|
| `@tombell/pi-plan` | Phase 2 (decide: keep-wrap vs own) | Internalizing plan mode needs the gating primitive (Phase 2) and ties it to plan-save / GitHub state; the thin loop (Phase 1) keeps borrowing it |
| `@juicesharp/rpiv-todo` | Phase 2 (→ perk checkpoints) or keep | Don't fake todos; once perk owns implement phases, checkpoints belong to perk |
| `@tombell/pi-diff`, status bar | Likely **keep** | Additive UX, no workflow authority — no reason to rebuild |

### Gallery evaluation

| Category | Packages | Default? |
|---|---|---|
| **Own — but study as prior art** | `@tombell/pi-plan` (plan mode), `@juicesharp/rpiv-pi` (whole five-skill workflow), `@plannotator/pi-extension` (plan/PR review UI) | No — perk's reason to exist. Read source; don't depend. |
| **Strong default candidates** (additive, low-risk) | `@juicesharp/rpiv-todo`, `@tombell/pi-status` or `pi-powerline-footer`, `@tombell/pi-diff` | Yes — curated set, recommended in scaffolded settings |
| **Recommend optionally / document** | subagents (`@tintinweb/pi-subagents`, `@gotgenes/pi-subagents`, `pi-subagents`), `pi-ask-user` / `@juicesharp/rpiv-ask-user-question`, `@gotgenes/pi-permission-system`, `pi-lens` / `pi-simplify` | No default; document as project-dependent add-ons |
| **Avoid defaulting** | `@plannotator/pi-extension` (heavy browser UI), `pi-crew` (competing orchestration), memory/web/MCP packages | No — out of scope or conflicts with "no dashboard in v1" |

## Non-goals (at least early)

- No Textual-style dashboard/TUI in v1 — use Pi's status lines, widgets, and custom
  messages first.
- No faking Claude's `ExitPlanMode` mechanism — preserve the behavioral contract (plan
  before writing), not the Claude-specific mechanism.
- No remote-planner / queue complexity before the interactive loop is solid.
- No bootstrap-dependence on heavy or competing workflow packages — borrow only thin,
  cheap-to-unwind pieces.
- No port of erk's **Python/Click/gateway/DI architecture** or **Textual TUI** — reimplement
  idiomatically in TypeScript/Pi; use Pi's status lines/widgets, not a dashboard
  (PRIOR_ART §11).
- No **Graphite stack machinery** (stacks, slot/worktree pools) in v1 — keep plain git +
  minimal worktrees; revisit only if stacking proves a real need.
- No **`erk exec`-style shelled-out CLI** as the engine — these become Pi extension tools.
  Keep the *contracts* (e.g., the `[{thread_id, comment}]` resolve-threads schema), drop
  the delivery mechanism.
- No **state encoded in branch names** (erk's legacy `P{issue}-`/`O{obj}-` prefixes) — the
  provider-agnostic plan ref is the sole source of truth from day one.

## Open decisions

1. **`@juicesharp/rpiv-pi`** — prior art, competitor, or foundation? Lean:
   study, don't bootstrap-depend. perk's GitHub-canonical workflow + objectives model is
   the differentiator; borrowing only `pi-plan` + `rpiv-todo` keeps internalization cheap.
2. **Plan mode** — reimplement natively or fork/wrap `@tombell/pi-plan`? Lean: borrow
   through Phase 1's thin loop, decide in Phase 2 from real usage (when the gating primitive
   lands with the CI executor).
3. **Objective status model** — erk uses a two-tier resolution (explicit status wins, else
   infer from the PR column) to serve both the parser and humans reading raw markdown, but
   this creates a "stale-status trap" on manual edits (PRIOR_ART §3). Lean:
   **explicit-status-only** unless human-editable raw tables are a hard requirement —
   simpler and trap-free.
4. **Minimum dogfoodable loop — RESOLVED toward the thin loop.** Phase 1 closes a *thin*
   end-to-end `plan → save → implement → ship` so **perk ships perk** before any deep stage
   work; objectives and CI depth move to Phase 2. This closes the dogfood loop earliest and
   validates plan storage/ref against a real implement/ship *before* investing in the
   objective factory — avoiding erk's over-build-then-consolidate trap. (Supersedes the
   earlier "plan-only until Phase 2" lean.)
5. **`init`/`doctor` delivery — RESOLVED (see [cli-vs-pi.md](./cli-vs-pi.md)).** perk ships
   a **Python `perk` CLI** (successor to `erk`) that owns the session *exterior*: `init`,
   `doctor`, worktree lifecycle, process launch (`perk <stage>`), and headless supervision.
   So `init`/`doctor` are real CLI commands (`perk init`, `perk doctor`), not slash
   commands. Bootstrap is shell-first: install the `perk` CLI, then `perk init` scaffolds
   the repo and `pi install -l`s the perk *extension* package. The extension still owns all
   in-session behavior; the two coordinate through durable state + process launch + a
   shared static schema, never in-process coupling. (The earlier slash-command lean is
   superseded.)
