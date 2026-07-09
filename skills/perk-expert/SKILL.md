---
name: perk-expert
description: Expert guidance on how perk works and how to configure and customize it in a repo that uses perk — `.perk/config.toml` tables and the local overlay, the six provider seams (plan/todo/askuser/footer/web/review), the GitHub vs Linear issue backend, skill bindings (`[[bindings]]`), CI checks (`[ci]` / `[[ci.checks]]`), the `[models]` namespace (default/per-stage/subagent model overrides), and worktree/base-branch settings. Use when answering "how does perk … / how do I configure … / which knob controls …" questions about a repo using perk, or when shaping perk's workflow behavior via config.
stages: [plan, objective-plan, objective-author]
references:
  - references/mental-model
  - references/configuration
  - references/providers-and-backends
  - references/customization-recipes
---

# perk expert (how it works · how to configure & customize)

perk is a **plan-oriented workflow on Pi**: work is organized around a written, reviewed plan that
travels a fixed spine (*objective → plan → save → implement → submit → address → land → learn*). This
skill is the on-demand expert on **how a repo configures and customizes perk's behavior** — the
`.perk/config.toml` surface, provider seams, the issue backend, skill bindings, CI checks, subagent model
overrides, and worktree/base-branch settings. It carries light orientation so a knob can be placed in
context.

## Always read the relevant reference before answering

**Never answer perk config/customization questions from memory or by guessing at a key, table, or
command.** For every such question: identify the relevant reference file(s) from the index below,
**read them**, then answer based on what you read. The config/provider surface is not introspectable
the way `--help` is, so the references are the source of truth in a consuming repo.

## How to discover the live surface

The references describe the **shape** of perk's surface. For the **exact current** command/flag set,
prefer asking perk itself over reciting commands from memory:

- `perk --help` / `perk <group> --help` — the live CLI surface (commands, groups, flags).
- `perk doctor` — validates `.perk/config.toml` + `[[bindings]]`, and reports provider/backend
  resolution (`plan=… todo=… askuser=… footer=… web=…`, the issue backend, Linear groups).
- `perk registry show` — the stage graph (the stages + their doors).
- `perk release-notes` — the bundled changelog's release notes (defaults to the running version;
  `--all`, `--version X.Y.Z`).
- In-session warm `/…` commands — the interior surface (e.g. `/plan`, `/submit`, `/ci`); list them
  with Pi's command surface inside a session.

Use these to confirm details rather than fabricating command/flag specifics.

## Reference Index

- [Mental model](./references/mental-model.md) — orientation: plan-oriented unit of work; the two
  planes (Python CLI exterior / TypeScript extension interior); the three state tiers (GitHub
  canonical / `.perk/workflow/` cache / session transient); stages + the warm/cold two-door model; the
  spine. Read first for "how does perk work / what is a stage / a door / a plane" questions.
- [Configuration](./references/configuration.md) — the `.perk/config.toml` committed config + the
  `.perk/local.toml` overlay and its semantics, then every table (`[models]` +
  `[models.stages.<id>]` / `[models.subagents]`, `[ci]` + `[[ci.checks]]`, `[workflow]`,
  `[worktree]`, `[[bindings]]`, `[issues]`, `[linear]`, `[providers]`, `[compaction]`) with
  key/type/default/notes. Read for "which key / what table /
  what default / how do the two files combine" questions.
- [Providers & issue backends](./references/providers-and-backends.md) — the six provider seams,
  the supported-provider catalog, the postures (REPLACE / AUGMENT / runtime-defer / vacate-only /
  DISPATCH),
  fallback semantics, and the Linear issue backend (auth, labels, identifiers, doctor groups,
  project-backed objectives, maturity). Read for "what providers exist / what does selecting X do /
  how do I use Linear" questions.
- [Customization recipes](./references/customization-recipes.md) — goal-oriented "change perk's
  behavior" recipes: attach a skill to a stage/command, set a repo default model, override a
  subagent model, configure CI checks, select a provider, switch to Linear, target a non-default
  base branch, write a custom subagent. Read for "how do I make perk do X" tasks.

## This is perk's own surface

These references describe **perk itself**. When working **in the perk repo**, the operator's full
canonical docs live under `docs/user-docs/` (each reference here names its canonical source in a
footer). In a repo that merely **uses** perk, `docs/user-docs/` is absent — the references here are
the source of truth.
