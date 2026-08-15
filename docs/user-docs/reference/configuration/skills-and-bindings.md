---
title: "Skills and bindings"
description: "The [skills], [[bindings]], and .perk/skills surfaces that scope and deliver repository guidance."
sidebar:
  order: 3035
---

# Skills and bindings

`[skills]` controls cold-launch exposure, `[[bindings]]` delivers named skills to stages and
commands, and `.perk/skills/` is the committed source for guidance authored by the repository.

## `[skills]`

Controls the **layered skills-exposure model**: which skills a cold stage launch (`perk plan`,
`perk implement`, and the other stage launchers) exposes to the session. Exposure resolves
through three layers for each skill:

1. A `[skills.stages]` row keyed by skill name wins when present.
2. Otherwise, the skill's `stages:` `SKILL.md` frontmatter applies: `all` or a list of stage ids,
   such as `stages: [plan, implement]`.
3. Otherwise, **undeclared means all stages**, preserving existing skills' behavior.

An explicit empty list (`stages: []` in frontmatter or a `= []` config row) hides a skill from
every stage launch, leaving it interactive-only. A malformed `stages:` frontmatter value falls
back to all stages with a warning. A skill **bound** to the launch's stage or command through
`[[bindings]]` is always exposed, trumping every layer, including an empty-list row.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `include_dirs` | array of strings | `[]` | Directories passed wholesale into scoped launches. `~` expands, and relative paths resolve against the repository root. |
| `include_packages` | boolean | package participation on | Whether npm-package skills, including pi-subagents, participate in scoped launches. |
| `[skills.stages]` | table | no rows | Skill name → `"all"` or a list of stage ids. Overrides the skill's own `stages:` frontmatter by narrowing or re-widening it. Ill-typed values fail config load; unknown skill names and stage ids are kept inert. |

```toml
[skills]
include_dirs = []
include_packages = true

[skills.stages]
ast-grep = ["implement", "address"]
dignified-python = "all"
librarian = []
```

The model **engages only when in use**: some skill declares `stages:` frontmatter, or any
`[skills]` content exists — a stages row, a non-empty `include_dirs`, or an explicitly set
`include_packages`. Perk's shipped skills declare `stages:` at source, so cold stage launches are
**scoped by default** once `.agents/skills/` is synchronized to the current perk with `perk init`
or `perk doctor --fix`. A repository whose mirror predates those declarations stays unscoped
(undeclared means all stages, fail-open) until the next synchronization.

> **Migration note — once engaged, global skills stop following you into stage sessions.** A
> scoped launch drops Pi's global or user skill directories (`~/.pi/agent/skills`,
> `~/.agents/skills`) and project `.pi/skills` by default. To keep a personal skill collection in
> perk sessions without committing it, whitelist the directory in the gitignored
> `.perk/local.toml`:
>
> ```toml
> [skills]
> include_dirs = ["~/.agents/skills"]
> ```

Scoping is composed only at cold launch. The whole composition is fail-open: any problem, such as
a not-yet-installed extension package, degrades that launch back to Pi's full skill discovery
with a warning and never blocks it. Bare interactive `pi` sessions and the remote runner are
untouched.

## `[[bindings]]`

An array-of-tables. Each row attaches one skill to a stage or command and delivers it into that
session. Every field is required; rows have no defaults.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `trigger` | string | _(required)_ | `"<kind>:<id>"`; `kind` is `stage` or `command`. |
| `skill` | string | _(required)_ | A skill installed under `.agents/skills/<name>/SKILL.md`. |
| `mode` | string | _(required)_ | `nudge` for a short pointer or `transclude` to inline the skill body. |

A user row at a trigger perk already binds **replaces perk's shipped default for that trigger**;
a row at a new trigger is added. The trigger overlay operates by trigger, not by skill name. The
binding recipe covers trigger selection, the nudge-versus-transclude decision, and the
model-deliverable command constraint.

```toml
[[bindings]]
trigger = "stage:implement"
skill = "house-style"
mode = "nudge"
```

## Repo-authored skills (`.perk/skills/`)

A repository can author its **own** skills. Put each one under
`.perk/skills/<name>/SKILL.md`, with a YAML frontmatter `name` matching the directory and a
`description`. `perk init` and `perk doctor --fix` discover them and render the managed
skills-CLI manifest fragment `.agents/manifest.d/perk-repo-skills.yaml` under a source pointing at
the repository's GitHub origin and default branch. perk never edits `.agents/manifest.yaml`; it
owns only its `.agents/manifest.d/` fragment.

The `perk skills` verbs drive the lifecycle:

- `scaffold NAME` writes a stub `SKILL.md` and reconverges the fragment.
- `create NAME` scaffolds and launches a write-capable authoring session.
- `refine NAME` re-opens an existing skill and skips synchronization.
- `delete NAME` removes the skill and reconverges.

The stub declares `stages: all` with a TODO comment. Narrow it deliberately to a stage-id list,
keep `all`, or use `[]` for interactive-only exposure; see [`[skills]`](#skills).

Because the source resolves the skill from the repository's **default branch**, a newly added
skill must be **committed and pushed** before the skills CLI can deliver it:

1. Add `.perk/skills/<name>/SKILL.md`.
2. Commit and push it to the default branch.
3. Re-run `perk init` or `perk doctor --fix`.

`perk init` is forgiving: a malformed `SKILL.md`, a name or source collision, or an uncommitted
skill produces a **non-fatal warning**. Init still exits zero and converges everything else.
`perk doctor` reports the same diagnostics through its `repo-skills` check: it **fails** for an
invalid `SKILL.md`, no GitHub remote, or fragment drift; it **warns** for an uncommitted skill, a
skill with undeclared `stages:` that is exposed to every stage launch, or a declared stage id
that is not a registry stage. The only fatal synchronization case is the skills CLI failing to
resolve a declared skill. The commit-push-synchronize sequence fixes it.

## Related

- **Do:** [How to attach a skill to a stage or command](../../how-to/attach-a-skill-to-a-stage.md) — choose a trigger and delivery mode.
- **Do:** [How to author a repo-specific skill](../../how-to/author-a-repo-skill.md) — create, publish, and synchronize repository guidance.
- **Look up:** [Configuration files](../configuration.md) — overlay semantics, value types, and the family map.
