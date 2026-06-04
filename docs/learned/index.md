---
title: docs/learned catalog
read_when: You need to find a durable learned doc, or you are authoring/refreshing one via /learn-docs.
---

# `docs/learned/` — the durable learnings catalog

This is the **full catalog** of perk's learned docs: token caches of cross-cutting reasoning for
future AI agents, consolidated from terminal `perk:learn` issues by the `/learn-docs` plan factory
(see the `perk-learn-docs` skill). Each doc lives under `docs/learned/<category>/` with light
frontmatter (`title` + `read_when`).

A **compressed routing index** of these docs is kept ambient in `.pi/APPEND_SYSTEM.md` (appended to
every session's system prompt); this file is the on-demand full listing that ambient index points
into. Both are maintained by `/learn-docs` plans — never by `perk init`.

## Documents

| Category | Document | Read when |
|---|---|---|
| workflow | [plan-factories.md](workflow/plan-factories.md) | Building or debugging a perk plan factory (learn-docs, objective-plan, any on-demand factory launching a read-only session) |
| workflow | [plan-ref-lifecycle.md](workflow/plan-ref-lifecycle.md) | Debugging plan-ref linkage, adding a worktree stage, extending PlanRef schema, or implementing on-land secondary bookkeeping |
| workflow | [init-doctor.md](workflow/init-doctor.md) | Adding a transient file to gitignore, writing a doctor migration, or extending init's managed gitignore block |
| pi | [context-system.md](pi/context-system.md) | Surfacing information to a plan session, building a factory, or debugging why a bash command is blocked in read-only mode |
| toolchain | [ruff.md](toolchain/ruff.md) | Debugging a CI-green / commit-rejected discrepancy, or a commit that silently didn't advance after a pre-commit hook |
