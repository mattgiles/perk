# erk Prior Art — Findings for perk

A systematic reading of erk's learned-knowledge corpus (the erk repo's `docs/learned/`),
distilled to what matters for building perk. erk is a Python/Click CLI wired into Claude
Code; perk is a Pi-native package. So this document keeps the **durable workflow model and
hard-won lessons** and discards the **Python/gateway/Textual implementation detail** that
will not port.

How to read: each section states *what erk does*, *the lesson*, and *implications for
perk* (the Pi mapping). Source files are under the erk repo's `docs/learned/`.

Companion docs: [RESEARCH.md](./RESEARCH.md) (architecture rationale),
ROADMAP.md (phasing).

---

## 1. The workflow model

erk's loop is **plan → save → dispatch → implement → finalize/merge**, wrapped by
**objectives** (multi-plan coordination) and **PR review / CI iteration**. The durable
insight is that the loop is a **state machine over GitHub-native artifacts**, with each
stage observable from GitHub state alone.

`planning/lifecycle.md` defines five phases and a "Which phase am I in?" table keyed on
observable GitHub state (labels, comments, PR draft status) plus a machine-readable
`lifecycle_stage` field. Stages: `prompted → planning → planned → impl` (terminal
`merged`/`closed` are inferred from PR state, not stored).

**Implications for perk:**
- Keep the loop and the state-machine framing. Make every transition an explicit
  command/tool (per RESEARCH's hard rule), not passive skill triggering.
- Reproduce the "reconstruct state from GitHub alone" property — it's what makes the
  workflow resumable, queue-able, and debuggable. Store a machine-readable stage but also
  keep it inferable from native GitHub state as a fallback.
- erk learned to **consolidate** stage values over time (`implementing`/`implemented` →
  single `impl`; see `planning/lifecycle-stage-consolidation.md`). Start with the fewest
  stages that are observably distinct.

---

## 2. Plan storage & schema

erk stores plans as **GitHub issues/PRs with a two-part metadata-block structure**
(`planning/plan-schema.md`, `lifecycle.md`, `architecture/metadata-blocks.md`):

- **Issue body** holds `plan-header` — compact YAML metadata, queryable without fetching
  comments (a separate API call).
- **First comment** holds `plan-body` — full plan content in a collapsible `<details>`.
- Blocks are delimited by HTML comments (`<!-- erk:metadata-block:plan-header -->`) and
  rendered as collapsible `<details>` so they're human-readable on GitHub yet
  machine-parseable.

Key mechanisms:
- **`plan-ref.json`** (`architecture/plan-ref-architecture.md`) is the *sole* source of
  truth mapping a plan to its branch. It is **provider-agnostic** (`provider`, `pr_id` as
  a **string** to allow non-numeric IDs like Jira `PROJ-123`, `url`, `labels`,
  `objective_id`). erk explicitly migrated away from encoding issue numbers in branch
  names and from a GitHub-specific `IssueReference`.
- **Session idempotency**: plan-save checks whether a plan already exists for the session
  ID and returns it rather than creating a duplicate (prevents retry-loop duplicates).
- **Field population is staged**: `branch_name`/`pr_number` are null during planning and
  only populated at submit. Commands must handle missing fields gracefully (LBYL).
- **Plan storage lookup priority**: explicit `--plan-file` → session scratch dir →
  fallback by mtime.

**Implications for perk:**
- Adopt the **two-part header/body split** and the **provider-agnostic ref** from day one
  — they are the single most reusable storage ideas. The string ID and provider field
  cheaply keep non-GitHub backends open.
- This directly informs ROADMAP's **plan-storage-model** foundational decision: erk itself
  moved toward "single canonical body + workflow-created PR." perk can adopt that
  simplification while keeping the header/body + ref discipline.
- In Pi, the local `plan-ref` equivalent lives in `.pi/workflow/` and the canonical
  copy in GitHub; transient session linkage uses `appendEntry`.
- Build idempotent save keyed on Pi session id.
- Line-number references in plans are **disallowed** (`planning/workflow.md`) — they drift.
  Require durable anchors (function names, behavioral descriptions). Worth encoding as a
  plan-authoring rule in a skill.

---

## 3. Objectives — "plan factories"

Objectives (`objectives/objective-lifecycle.md`, `objective-storage-format.md`,
`roadmap-status-system.md`) are the multi-plan coordination layer. The durable design:

- An objective is a long-running goal that **generates bounded plans** rather than being
  implemented directly. State machine: `Created → Active → Complete → Closed`; steps:
  `pending → planning → in_progress → done | skipped | blocked`.
- **Dual storage, single source of truth**: YAML frontmatter (in issue body) is canonical;
  a rendered markdown table (in a comment) is for humans. Mutations update both atomically;
  reads only parse the frontmatter. Steps are a **flat list**; phase membership is derived
  from ID prefix (`1.2` → phase 1); phase names live only in markdown headers.
- **Two-tier status resolution** (`roadmap-status-system.md`): explicit status wins;
  otherwise infer from the PR column (`#123` → `in_progress`, never `done` without
  confirmation; empty → `pending`). This serves two audiences — the parser (deterministic)
  and humans reading raw markdown. The asymmetry: *mutation writes both cells, parsing
  reads one* — manual edits create a stale-status trap, fixed by resetting status to `-`.
- **Body reconciliation tiers**: Mechanical (status/PR cells, by command) / Reconcilable
  (Design Decisions, step descriptions, by LLM after a PR overrides intent) / Immutable
  (Exploration Notes, never touched). After each PR lands, an agent reconciles stale prose
  against what was actually built — "roadmap is a source of truth for *what exists*, not
  just *what was intended*."
- **Dependency-graph next-node selection** with a three-tier fallback
  (`pending → planning → in_progress`).

**Implications for perk:**
- Port objectives as a first-class concept — it's a genuine differentiator over the simpler
  gallery workflows. Keep the **frontmatter-canonical / table-rendered** split and the
  **flat-list-with-derived-phases** model.
- The two-tier status system is subtle but high-value; if perk simplifies, prefer
  **explicit status only** (avoids the stale-status trap) unless human-readable raw tables
  are a hard requirement.
- Reconciliation-after-landing is a strong idea worth keeping: an extension command that,
  post-merge, asks the model to reconcile objective prose against the merged PR.
- The objective skill is already flagged in RESEARCH as a high-value port; this corpus
  confirms the *mechanics* (storage, mutation sites, status) belong in deterministic
  extension tools, while the *judgment* (which nodes a PR completed, prose reconciliation)
  stays in skills/prompts.

---

## 4. PR operations

`pr-operations/pr-submit-phases.md` defines a 5-phase submit: create/update PR → gather
diff + plan context (concurrently) → AI-generate title/body → optional stack metadata →
push metadata. Notable durable patterns:

- **Plan context flows into the PR**: the generator receives the linked plan so the
  description matches original intent; the full plan is embedded in a collapsible
  `<details>` in the PR body but **not** in the commit message (two-target pattern: plain
  commit message vs HTML-enhanced GitHub body).
- **Validation rules** (`pr-validation-rules.md`, `pr-commands.md`): PR bodies need a
  checkout footer in plain backtick form — HTML `<details>` breaks footer validation.
  There's an explicit `pr check` validation step.
- **Draft PRs** mark plan-only/in-progress work; "ready for review" is a deliberate
  transition that triggers reviews. A PR can be open with *only* plan files and no
  implementation — don't infer completion from PR state alone; diff for changes outside the
  impl folder.

**Implications for perk:**
- Keep "feed plan context into PR generation" and the **commit-message vs PR-body** split.
- Make `pr-submit`/`pr check` deterministic extension surfaces (RESEARCH already calls
  this out). Shell `gh` first, harden later.
- Draft-vs-ready as the review gate maps cleanly onto perk's ship flow.

---

## 5. Review handling & CI iteration

Two of the strongest, most portable ideas in the whole corpus:

**The devrun read-only separation** (`ci/ci-iteration.md`): CI commands run in a
**read-only agent that has no Edit/Write tools** (enforced by the SDK, not prompts). The
cycle is **Run → Report → Fix → Verify**: the executor reports failures, the *parent* agent
analyzes and fixes, then the executor re-verifies. This structurally prevents the
"auto-fix trap" (suppressing warnings, broad excepts, blind `--fix`) and isolates noisy
test output from the main context window. Prompts like "run tests and fix them" are
forbidden; "run tests and report results" is required.

**Feedback classification** (`pr-operations/feedback-classification.md`,
`erk/pr-address-workflows.md`): review feedback is classified
(**actionable / informational / praise / question**) before acting — only actionable items
need code changes. `pr-address` runs phases: fetch+classify → generate fixes → apply →
resolve threads. A preview variant runs classification only. Thread resolution is a
**deterministic batched operation** with a strict JSON schema
(`[{thread_id, comment}]` — not a flat list; `resolve-review-threads-format.md`). Review
threads vs discussion comments are different GitHub APIs and counted separately.

**Automated reviews** (`ci/automated-review-system.md`): convention-based review bots
discovered by changed-file patterns, run in parallel on non-draft PRs, separate from the
repo's own `ci.yml`. Bot threads inflate "informational" counts (expected).

**Plan File Mode** (`pr-address-workflows.md`): when a PR's diff is just a tracked
`plan.md`, pr-address reinterprets all feedback as "edit the plan text," not "implement it."

**Implications for perk:**
- The devrun pattern maps beautifully onto Pi's **`setActiveTools` / tool gating**: a CI
  iteration mode (or sub-run) with `read`/`grep`/`bash`-read-only, no `edit`/`write`. This
  is the same gating machinery as plan mode — build it once, reuse.
- Port feedback classification + batched, schema'd thread resolution as deterministic
  extension tools; keep the classification *judgment* in a skill/prompt.
- Reuse the Run→Report→Fix→Verify loop shape for perk's CI iteration; don't let the model
  fix and run in one undifferentiated step.

---

## 6. Context injection & skills design — validates and sharpens RESEARCH

This is the most important cross-cutting finding and it directly reinforces RESEARCH's
"don't over-rely on skills" thesis with **data**.

`documentation/passive-context-vs-retrieval.md` (citing Vercel's agent evals):

| Approach | Pass rate |
|---|---|
| No docs (baseline) | 53% |
| Skills (default invocation) | 53% |
| Skills (explicit "use them" instructions) | 79% (brittle) |
| Compressed index in AGENTS.md | 100% |

The **retrieval paradox**: an agent can't distinguish stale training data from correct
knowledge, so it won't invoke a skill it doesn't know it needs. Skills with default
invocation perform *identically to no documentation*.

erk's answer is a **three-tier context architecture**
(`architecture/context-injection-tiers.md`, `hooks/reminder-consolidation.md`):

1. **Ambient** (AGENTS.md / `@`-embedded index) — always present, ~100% compliance, paid
   once per session. For universal rules and "what exists" awareness.
2. **Per-prompt** (UserPromptSubmit hook) — session-wide routing + dynamic state (session
   id, branch). Paid per turn.
3. **Just-in-time** (PreToolUse hook) — fires only before a specific tool/file type; can
   inspect params and block. Highest signal, lowest cost.

Consolidation rule: every reminder appears **exactly once at the most specific tier**;
keep content at multiple tiers only when each delivers genuinely different content
(compressed ambient awareness + pointed JIT nudge).

`commands/tool-restriction-safety.md`: safety is **structural, not prompted** —
`allowed-tools` allowlists make read-only commands actually read-only, the runtime enforces
it, and restrictions **cascade transitively** to delegated subagents. This is the mechanism
behind safe in-plan-mode commands.

`claude-code/skill-composition-patterns.md`: skills persist for the whole session (don't
defensively reload); extract reusable prompt content into a referenced inner skill/reference
file; guideline-only skills work via composition but **fail when forked** to a subagent
(subagents execute tasks, not absorb ambient knowledge).

**Implications for perk:**
- This is the empirical backbone for RESEARCH's split. Concretely for Pi:
  - **Ambient** → `AGENTS.md` + Pi context files; keep a compressed index, not 40KB of prose.
  - **Per-prompt** → `before_agent_start` system-prompt injection / `input` event.
  - **Just-in-time** → `tool_call` event (inspect params, inject reminder, or block) — the
    Pi analogue of PreToolUse, and the home for write-policy/plan-mode gating.
- Treat **skills as opt-in expertise the user or a command invokes**, never as the carrier
  of a critical transition. Make workflow boundaries commands/tools.
- Reuse Pi's tool gating (`setActiveTools`, `tool_call` blocking) as the structural safety
  mechanism for both plan mode and CI mode.
- Keep reminders consolidated to one tier; don't duplicate across `AGENTS.md`, system
  prompt, and tool_call.

---

## 7. Hooks → Pi events mapping

erk's Claude hook wiring (`hooks/`) maps cleanly onto Pi extension events. Two distinct
hook kinds matter:

- **Claude Code hooks** (shell/JSON): UserPromptSubmit, PreToolUse, PostToolUse.
- **Prompt hooks** (`hooks/prompt-hooks.md`): markdown files at `.erk/prompt-hooks/*.md`
  that are **AI-readable instructions injected at workflow points**, executed by the agent
  rather than the shell. Key ones: `post-init.md` (project setup after init — the dogfood
  handoff), `post-plan-implement-ci.md` (CI strategy after implementation).

| erk hook | Pi event |
|---|---|
| UserPromptSubmit | `input` / `before_agent_start` |
| PreToolUse (inspect/block) | `tool_call` |
| PostToolUse (format edited files) | `tool_result` |
| ExitPlanMode transition | explicit Pi command (`/implement`, `/approve-plan`) |
| Prompt hooks (`.erk/prompt-hooks/*.md`) | extension-read markdown injected via `before_agent_start` at the right workflow point |

**Implications for perk:**
- The **prompt-hooks-as-project-config** idea is excellent and already in ROADMAP Phase 0
  (post-init handoff) and Phase 2 (CI prompt config). Preserve it: project-local markdown
  the extension injects at defined points, distinct from shell hooks.
- erk's PostToolUse formatter (Ruff on edited `.py`) → Pi `tool_result` middleware that runs
  a formatter deterministically after edits.

---

## 8. State, markers, and scratch storage

- **Workflow markers** (`planning/workflow-markers.md`): session-scoped key/value state
  passed *between workflow steps within a session* (e.g., `objective-context`,
  `roadmap-step`, `plan-saved-issue`). Survive hook boundaries, not restarts. The
  `objective-context` marker is the *only* mechanism linking a plan to its objective and
  must be set before entering plan mode — a documented silent-failure trap.
- **Scratch storage** (`planning/scratch-storage.md`): worktree+session-scoped
  `.erk/scratch/sessions/<id>/` for inter-process AI workflow files (diffs, generated
  bodies), distinct from `/tmp`. Large sessions get preprocessed (~99% token reduction)
  before analysis.
- **Three-tier state** overall: GitHub (canonical) / local impl-context + scratch
  (materialized cache) / session markers (transient linkage).

**Implications for perk:**
- This is exactly RESEARCH/ROADMAP's three-tier state contract, validated. Pi mapping:
  GitHub canonical / `.pi/workflow/` cache / session `appendEntry` for markers.
- erk's markers map to Pi `appendEntry` custom entries restored on `session_start`. Note
  the lesson: make objective↔plan linkage **explicit and verified** (erk's tripwire warns
  it fails silently) — don't rely on a marker being set at the right moment without a check.
- Adopt session-scoped scratch under `.pi/workflow/` and a preprocessing step for large
  session analysis if perk does learn-style session capture.

---

## 9. Capability system, init & doctor

`architecture/capability-system.md` + the init/doctor commands (already examined for
ROADMAP Phase 0):

- **Capabilities** are installable features (skills, workflows, settings, docs) tracked in
  `.erk/state.toml`. **Required** ones auto-install on init and are always checked by
  doctor; **optional** ones are checked only if installed. They're **backend-aware**
  (`supported_backends`), enabling claude/codex filtering.
- doctor filters artifact health checks by installed capabilities (`None` = check all,
  inside erk's own repo; a frozenset = consumer repos).
- Config is layered: global / repo (shared) / local (gitignored, per-user) with documented
  merge semantics.

**Implications for perk:**
- Pi's package/resource model already covers much of "capabilities" (extensions, skills,
  prompts bundled and selectively enabled via settings). perk's `init`/`doctor` should
  track *which optional perk pieces and which borrowed packages* are enabled, and
  health-check accordingly — the required-vs-optional and "check only what's installed"
  distinction ports directly.
- The global/repo/local config split maps onto user `~/.pi/agent/settings.json` vs project
  `.pi/settings.json` plus a gitignored local layer — informs ROADMAP's state-tiering and
  the `.gitignore` management in `/perk-init`.

---

## 10. Multi-backend portability — the deepest validation of perk's premise

`integrations/multi-agent-portability.md` and `integrations/codex/*` are erk's own
"don't build a Claude clone" research, and they map almost 1:1 onto Pi:

- **Plan mode**: Claude has a built-in `EnterPlanMode` tool; Codex has *no equivalent*
  (agent-managed). erk concluded plan mode must be a behavioral contract, not a
  mechanism — exactly RESEARCH's stance for Pi.
- **Session tracking**: `CLAUDE_SESSION_ID` env var is Claude-specific; Codex has no env
  var (internal ThreadId via events/API). erk learned not to depend on it. **Pi gives perk
  first-class session entries** — strictly better; don't recreate `CLAUDE_SESSION_ID`
  dependence.
- **Permission models differ** (Claude single-axis `--permission-mode` incl. `plan`; Codex
  dual-axis sandbox+approval). erk maps an internal `PermissionMode` across both. perk
  should own a small internal mode concept and implement it via Pi tool gating rather than
  any backend's permission UI.
- **Skills/AGENTS.md/non-interactive execution are structurally similar** across backends;
  the variation is metadata/scope/injection. erk's takeaway: keep a **declarative registry
  that generates per-backend artifacts**. For perk, Pi is the single backend, so this
  collapses — but it confirms keeping workflow logic in the extension (portable) and only
  the thin artifact layer harness-specific.

**Implications for perk:** Pi's primitives (session entries, tool gating, extension events)
are the very abstractions erk had to hand-roll across backends. perk gets them natively —
which is the core argument for the Pi-native rebuild.

---

## 11. What NOT to carry over

- **Python/Click/gateway/DI architecture** (`architecture/*`, most of `cli/*`,
  `testing/*`): ABCs, fakes, dry-run wrappers, Click context DI, re-export rules — all
  Python-specific. perk is TypeScript/Pi; reimplement idiomatically.
- **Textual TUI / dashboard** (`tui/*`, `textual/*`): explicit non-goal for perk v1
  (RESEARCH). Use Pi status lines, widgets, custom messages first.
- **Graphite stack machinery** (`erk/graphite-*`, stacks, slot pools, worktree pools):
  heavy and Graphite-specific. perk should keep plain git + worktrees minimal; revisit only
  if stacking is a real need.
- **Claude-specific hook wiring and `CLAUDE_SESSION_ID`**: replaced by Pi events + session
  entries.
- **erk's exec-script CLI surface** (`erk exec ...`): these become Pi extension tools, not
  a shelled-out Python binary. Keep the *contracts* (e.g., the resolve-threads JSON schema),
  not the delivery mechanism.
- **Branch-name-encoded metadata** (legacy `P{issue}-`/`O{obj}-` prefixes): erk itself
  moved to `plan-ref.json` as sole source of truth. Start there; don't encode state in
  branch names.

---

## 12. Decisions perk inherits (with leanings)

1. **Plan storage**: two-part header/body + provider-agnostic ref. Lean toward erk's *newer*
   "single canonical body + workflow-created PR" simplification (feeds ROADMAP foundational
   decision #2).
2. **Objective status model**: keep objectives; lean **explicit-status-only** to dodge the
   two-tier stale-status trap unless raw-markdown human editing is required.
3. **Context strategy**: ambient (AGENTS.md compressed index) + JIT (`tool_call`) as the
   compliance backbone; skills are opt-in expertise, never transition carriers. (Backed by
   the Vercel eval data.)
4. **Safety is structural**: plan mode *and* CI mode are the same Pi tool-gating mechanism
   (read-only allowlist + `tool_call` blocking), not prompt instructions.
5. **CI iteration**: preserve the read-only executor + Run→Report→Fix→Verify separation via
   tool gating / sub-runs.
6. **Review handling**: classify-then-act, batched schema'd thread resolution, draft→ready
   as the review gate — all deterministic extension surfaces.
7. **Project config as prompt hooks**: markdown injected at workflow points
   (post-init handoff, CI strategy) stays; it's how perk dogfoods and stays customizable.
8. **State tiers**: GitHub canonical / `.pi/workflow/` cache / session `appendEntry`
   markers — with explicit, *verified* objective↔plan linkage (erk's silent-failure lesson).
