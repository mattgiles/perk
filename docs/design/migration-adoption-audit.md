# Migration/adoption audit — erk's migration surface vs. perk's issue-canonical model

**Status:** decided — audit complete (Objective #137, Node 4.2). Outcome: adopt nothing in code.

This node was an *audit-and-adopt, not a blanket port*. It systematically surveyed erk's
migration + adoption surface — the four surfaces the ROADMAP named (import existing
planned/draft-PR plans, translate objective markers, map residual `.claude` references, session
import) plus the adjacent adoption surface — and decided, surface by surface, what perk **adopts**
vs. **drops**. The survey concluded perk has **no migration burden worth tooling**: every surface
is either already adopted as a *pattern* in perk, or a deliberate drop because perk's clean
Pi-native, issue-canonical model gives it nothing to migrate. The value of this node is the
*recorded decision* below — not new machinery.

## Why perk has (almost) no migration surface

erk was wired **into Claude Code**, so its entire workflow surface lived under `.claude/`
(`.prior-art/erk/.claude/` contains `agents/`, `commands/`, `hooks/`, `settings.json`, `skills/`).
perk is **Pi-native**: it lives entirely under `.pi/` and reads **nothing** from `.claude/` —
verified by grepping `\.claude` across `perk/**/*.py`, which returns **no matches**.

perk is also **issue-canonical from day one** and starts its **own** schema at v1
(`perk/objective.py`: `OBJECTIVE_SCHEMA_VERSION = "1"`, with the module comment stating perk
"does not inherit erk's 2/3/4"). There is therefore no legacy *perk* artifact in any surface to
convert — perk never stored plans as draft PRs, never wrote `.claude/` wiring, and never emitted a
pre-v1 objective.

The only conceivable migration *source* is an **external erk repo** — a one-shot, hand-doable
event, not a product surface. Building importers/migrators for it would be drift-prone fiction with
no real corpus to test against, which violates AGENTS.md's "**don't author fiction for unbuilt
components**". The audit therefore adopts nothing in code; where knowledge would otherwise be lost
(e.g. the hypothetical one-shot plan import), it is preserved as a *manual procedure* below.

## Decision table

| Surface | erk artifact (evidence) | perk's model today | Decision | Why |
|---|---|---|---|---|
| 1. Import draft-PR plans | `.prior-art/erk/packages/erk-shared/src/erk_shared/pr_store/` (`create_plan_draft_pr.py`, `planned_pr_lifecycle.py`, `planned_pr.py`, `conversion.py`, `backend.py`, `types.py`); `erk_shared/impl_folder.py` | Issue-canonical: `perk/plan.py` (metadata-block header/body) + `perk/cache.py` (`plan-ref.json` mirror) | **DROP** | No perk draft-PR artifacts ever existed; an external-erk import is a one-shot hand migration, not worth a drift-prone importer with no test corpus |
| 2. Translate objective markers | `.prior-art/erk/src/erk/cli/commands/exec/scripts/migrate_objective_schema.py` (v2/v3→v4 converger); `erk_shared/gateway/github/metadata/roadmap.py` | `perk/objective.py`: `OBJECTIVE_SCHEMA_VERSION="1"`, writer emits latest (`render`), parser version-gates ("unsupported schema_version") | **ADOPTED (pattern) + DROP (migrator)** | The version-gating pattern is already in perk; no legacy perk objectives exist, so an in-place migrator is unneeded at v1 |
| 3. Residual `.claude` references | `.prior-art/erk/.claude/settings.json` (hooks → `erk exec …`), `.claude/commands/erk/`, `.claude/agents/`, `.claude/hooks/`; artifact-sync (`src/erk/cli/commands/artifact/`) | Zero `.claude/` references in `perk/**/*.py`; only `.claude` here is `.gitignore`'s `/.claude/skills/` (the skills-tool runtime) | **DROP** (incl. rejected doctor check) | perk reads nothing from `.claude/`; inert artifacts are harmless; a standing advisory check wasn't judged worth the noise |
| 4. Session import | `.prior-art/erk/src/erk/cli/commands/cc/session/` (`list_cmd.py`, `show_cmd.py`) reading `~/.claude/projects/` JSONL via `erk_shared.extraction.claude_code_session_store` | No Claude Code sessions exist in a Pi-native repo; the analogue is the unbuilt `docs/design/session-introspection.md` (a reader over **pi** session JSONL) | **DROP** (Claude import) + **DEFER** (Pi introspection) | Nothing to read; the Pi analogue is a separate, larger, loosely-coupled effort |
| Adjacent: `erk artifact sync/check/list/show` | `.prior-art/erk/src/erk/cli/commands/artifact/` (`sync_cmd.py`, `check.py`, `list_cmd.py`, `show.py`) | `perk init` forward-converges into `.pi/` | **DROP** | No `.claude/` artifacts to sync; convergence is `init`'s job |
| Adjacent: bootstrap-from-erk-repo | RESEARCH.md §1 ("inspect an existing erk repo and generate Pi config") — never built | `perk/init.py` forward-converges, has no erk-inspection (grep `\.erk\|bootstrap\|inspect` → no matches) | **DROP** | `init` is a forward-converging path, never an erk-importer |

## Surface 1 — Import draft-PR plans → issue-canonical

**What erk does.** erk stored plans as **draft PRs**. The machinery lives in
`.prior-art/erk/packages/erk-shared/src/erk_shared/pr_store/`: `create_plan_draft_pr.py` opens the
draft PR, `planned_pr_lifecycle.py` / `planned_pr.py` model its lifecycle, `conversion.py` converts
between shapes, and `backend.py` / `types.py` carry the storage backend and types. An impl-folder
surface (`erk_shared/impl_folder.py`) accompanied it. PRIOR_ART.md §2 records that erk itself moved
toward a "single canonical body + workflow-created PR" model.

**What perk has today.** perk is **issue-canonical from day one**: `perk/plan.py` is the
metadata-block header/body engine (the plan *is* a GitHub issue), and `perk/cache.py` maintains the
`plan-ref.json` local mirror. perk **never** stored plans as draft PRs, so there is no legacy perk
artifact to convert.

**Decision: DROP.** No perk draft-PR artifacts ever existed. The only scenario where import matters
is a one-shot migration *from an external erk repo* — rare, hand-doable, and impossible to test
against without a real corpus. A draft-PR→issue importer command would be drift-prone fiction.

**Manual procedure (the hypothetical one-shot case).** If a real external erk repo ever needs a
plan migrated, do it by hand — no tool required:

1. Open the erk draft PR and read its plan body (the canonical plan text).
2. Create a perk plan issue from that text via `perk plan-save` (cold door) or the `plan_save`
   tool (warm door) — perk writes the metadata-block header/body and mints the `plan-ref`.
3. Re-point the implementation branch at the new perk plan (set the branch's upstream / open the
   perk PR against the new issue), then close the old erk draft PR.

This knowledge is recorded here precisely so it is not lost despite no tool being built.

## Surface 2 — Translate objective markers

**What erk does.** `.prior-art/erk/src/erk/cli/commands/exec/scripts/migrate_objective_schema.py`
is an **in-place schema-version converger** (v2/v3 → v4 frontmatter), surfaced as
`.claude/commands/erk/migrate-objective-schema.md`. erk's roadmap blocks carry a `schema_version`
and are parsed by `erk_shared/gateway/github/metadata/roadmap.py`.

**What perk has today.** `perk/objective.py` already implements the *valuable pattern* behind that
migrator: a single `OBJECTIVE_SCHEMA_VERSION = "1"`, a writer that always emits the current version
(`render`), and a parser that **version-gates** — it rejects any mismatch with "unsupported
schema_version". The module comment is explicit: perk "starts its OWN objective schema at 1 — it
does not inherit erk's 2/3/4."

**Decision: ADOPTED (pattern) + DROP (the migrator).** perk's writer-emits-latest +
version-gating-parser design *is* the durable lesson from erk's `migrate_objective_schema.py`. No
legacy perk objectives exist (perk is at v1), so an in-place migrator has nothing to convert and is
unneeded. erk's `migrate_objective_schema.py` is the **template to mirror** if/when perk ever ships
schema "2".

## Surface 3 — Residual `.claude` references

**What erk does.** erk's `.claude/settings.json` registered Claude Code hooks
(`UserPromptSubmit` / `PreToolUse` / `PostToolUse` → `erk exec …`; see RESEARCH.md §15), alongside
`.claude/commands/erk/`, `.claude/agents/`, `.claude/hooks/`, and an artifact-sync surface
(`.prior-art/erk/src/erk/cli/commands/artifact/`).

**What perk has today.** **Zero** `.claude` references in perk's code (`grep \.claude perk/**/*.py`
→ no matches). The only `.claude` mention anywhere in this repo is `.gitignore`'s
`/.claude/skills/`, which is owned by the **dignified skills tool** runtime (the "skills managed
runtime artifacts" gitignore block) — **not** erk. This repo's `.claude/` directory contains only
`skills/`.

**Decision: DROP — including the considered-and-rejected `doctor` advisory check.** A
`perk doctor` advisory was the **lone code candidate** in this entire audit. It would have `warn`ed
on erk-shaped wiring (`.claude/settings.json` hooks, `.claude/commands/`, `.claude/agents/`) while
excluding the legitimate `.claude/skills/` runtime dir. It was **weighed and explicitly rejected**:
the migration-from-erk scenario is rare and one-shot, and the standing advisory noise was not judged
worth the maintenance. Inert `.claude/` artifacts are harmless, and a user can delete them manually.
This is recorded as considered-and-rejected, not silently omitted.

## Surface 4 — Session import

**What erk does.** `.prior-art/erk/src/erk/cli/commands/cc/session/` (`list_cmd.py`,
`show_cmd.py`) reads Claude Code JSONL sessions from `~/.claude/projects/` via
`erk_shared.extraction.claude_code_session_store` (a `ClaudeCodeSessionStore` ABC with `Real` /
`Fake` implementations).

**What perk has today.** A Pi-native repo has **no Claude Code sessions** — erk's `cc/session`
import has nothing to read. perk's analogue is the **unbuilt** session-introspection design at
`docs/design/session-introspection.md`, a read-only reader over **pi** session JSONL.

**Decision: DROP (Claude-session import) + DEFER (Pi introspection).** There are no Claude Code
sessions to import in a Pi-native repo, so erk's importer is moot. The Pi-native analogue is a
separate, larger, loosely-coupled effort tracked by its own design doc — link it and defer
(record-only, see below).

## Adjacent adoption surface (swept for completeness)

Both adjacent surfaces are drops:

- **`erk artifact sync/check/list/show`** (`.prior-art/erk/src/erk/cli/commands/artifact/` —
  `sync_cmd.py`, `check.py`, `list_cmd.py`, `show.py`) syncs `.claude/` artifacts from the
  installed erk package. perk manages its surface via `perk init`'s forward convergence into
  `.pi/`; there are no `.claude/` artifacts to sync. **DROP.**
- **The never-built bootstrap-from-erk-repo idea** (RESEARCH.md §1: "a bootstrap command that can
  inspect an existing erk repo and generate Pi config"). Verified **not built**: grepping
  `\.erk|bootstrap|inspect` in `perk/init.py` returns no matches. perk's `init` is
  forward-converging, never an erk-importer. **DROP.**

## Recommended follow-on (record-only)

These are **recorded, not created** — no GitHub issues or objective nodes are spawned by this work.
Spawning any of them stays a human decision (durable-write/spawn judgment stays with the human):

1. **Build Pi session-introspection** per `docs/design/session-introspection.md` (the Pi-native
   analogue of erk's `cc/session` reader).
2. **A one-shot draft-PR→issue plan importer** — *only if* a real external erk repo ever needs
   migrating, and even then weigh it against the manual procedure in Surface 1.
3. **An objective schema-2 migrator** (template: erk's `migrate_objective_schema.py`) — *only when*
   perk's objective schema actually bumps past v1.

## Non-goals / explicitly dropped

- **No** draft-PR→issue plan importer command/tool.
- **No** objective schema migrator (perk is at schema 1; nothing to migrate).
- **No** `doctor` / `init` changes — including the rejected `.claude`-residue advisory check.
- **No** Claude-Code session-import command.
- **No** new GitHub issues or objective nodes spawned by this work (record-only follow-on).
- **No** edits to `docs/ROADMAP.md` or other historical planning docs (history is preserved; this
  audit doc is the new source of truth for the decision).
