---
name: perk-skill-author
description: Authoring a repo-specific skill via `perk skills create`/`refine` — write a concrete `description`, prefer scripts/references over prose, keep delivery self-contained, validate frontmatter, and update bindings/docs only when directly required. Use when authoring or refining a repo-authored skill.
---

# Authoring a repo-specific skill

A repo-authored skill lives at `.perk/skills/NAME/SKILL.md` in the main checkout and is delivered to
sessions through the skills-CLI manifest. `perk skills create NAME` pre-scaffolds the directory and
launches a write-capable session (this one) to author it; `perk skills refine NAME` re-opens an
existing skill to sharpen it. **This skill is the judgment layer** — what makes a skill discoverable,
lean, and self-contained. Judgment, authoring, and the decision to commit stay with **you**.

## The soft scope

You are authoring **one skill**: `.perk/skills/NAME/SKILL.md` (already scaffolded) plus any sibling
`references/`/`scripts/` files it needs, and — only when the skill must fire at a stage or command —
the bindings/docs that wire it. perk has no structural write-sandbox, so this scope is a
**discipline, not a sandbox**: don't touch unrelated files. **Leave committing to the user** — author
the skill, then stop.

## Write a concrete `description`

The `description` is the *entire* discovery surface — Pi matches a task against it to decide whether
to surface the skill. A vague topic label ("Python helpers") never fires; a concrete trigger does.

- **Name the tasks and trigger phrases**, not the subject area. Lead with what the skill *does*, end
  with an explicit "Use when …" clause naming the situations that should activate it.
- Mirror the words a user or agent would actually use for the task.
- Keep it one or two sentences — long enough to be concrete, short enough to scan.

## Prefer scripts/references over prose

Keep `SKILL.md` **lean** — durable judgment and the loop, not an encyclopedia. Heavy or reference
material (long tables, API dumps, worked examples, helper scripts) goes in **sibling files** under
`references/` or `scripts/`. The per-skill delivery symlink carries the whole skill directory, so
those siblings travel for free — reference them by relative path from `SKILL.md`. A wall of prose is
harder to apply than a tight body that points at the detail when it's needed.

## Keep delivery self-contained

A delivered skill lands in repos where perk's own `docs/` may be **absent**. Don't assume any file
outside the skill directory exists at read time.

- **Mirror what the skill needs** into the skill directory rather than linking to repo docs that may
  not ship with it.
- When you must cite a canonical source, link it explicitly (a URL or a clearly-named path) and
  summarize the essential point inline so the skill still stands alone if the link is unreachable.

## Validate the frontmatter

The convergence enforces two rules — get them right or the skill won't render into the manifest:

- **`name` must equal the directory segment** (`.perk/skills/NAME/` ⇒ `name: NAME`).
- **`description` must be non-empty** (and, per above, concrete).

Replace the scaffold's `TODO` placeholder `description` before you finish — a left-over placeholder
is non-empty but useless for discovery.

## Update bindings/docs only when required

Most skills are **ambient**: Pi discovers them by `description` match, with no wiring. Add a binding
**only when the skill must fire deterministically** at a perk stage or command:

- Add a `[[bindings]]` entry (repo overlay in `.pi/perk.toml`) or a `shared/bindings.yaml` entry
  (a shipped default) with the right `trigger` (`stage:<id>` / `command:<id>`) and `mode`
  (`nudge`/`transclude`).
- When you touch user-facing behavior, **reconcile the docs in the same change** — don't let them
  drift.

Don't wire bindings the skill doesn't need; ambient discovery via a good `description` is the default.
