---
title: "How to author a repo-specific skill"
description: "Author a skill that lives in this repo so its guidance travels with the repo and is delivered like any installed skill."
sidebar:
  order: 2270
sidebarGroup: "Customization"
---

# How to author a repo-specific skill

Create a skill under `.perk/skills/`, publish it on the repository's default branch, and synchronize
its installed link.

## Prerequisites

Run `perk init` once and make sure the repository has a GitHub origin. The
[repo-authored skills configuration](../reference/configuration/skills-and-bindings.md#repo-authored-skills-perkskills)
uses that origin to resolve committed skill content.

## Steps

1. **Create the skill once.** Choose one create-only command:

   ```bash
   perk skills scaffold my-skill
   ```

   This writes a manual starter at `.perk/skills/my-skill/SKILL.md`. For a guided, write-capable
   authoring session instead, run:

   ```bash
   perk skills create my-skill
   ```

   Both commands refuse a name whose `.perk/skills/my-skill/` directory already exists. Use
   `perk skills refine my-skill` for an existing skill rather than overwriting it.
2. **Edit the source file.** Complete `.perk/skills/my-skill/SKILL.md`. Keep its frontmatter `name`
   equal to the directory name and give it a non-empty, task-specific `description`.
3. **Publish the source.** Commit the skill and push it to the repository's default branch. The
   managed skills source resolves from that branch, so local or merely unpushed content cannot be
   fetched by the synchronization step.
4. **Synchronize delivery.** Run:

   ```bash
   perk skills sync
   ```

   Verify that `.agents/skills/my-skill/SKILL.md` now resolves to the committed skill. This is the
   installed path that Pi and perk binding delivery read.
5. **Reopen it later.** Run `perk skills refine my-skill` to improve the existing source in another
   guided session. Commit, push, and sync the revision again.
6. **Remove it deliberately.** Run `perk skills delete my-skill`, review the path in the confirmation
   prompt, and confirm. Use `--yes` only when you intentionally need non-interactive confirmation.
   Commit and push the removal.

## Expected result

The source stays versioned at `.perk/skills/my-skill/`, while the synchronized
`.agents/skills/my-skill` installation makes it available to Pi and to `[[bindings]]` delivery.

## Related

- **Do:** [Attach a skill to a stage](./attach-a-skill-to-a-stage.md) — deliver the synchronized
  skill.
- **Look up:** [`perk skills`](../reference/cli.md#perk-skills-alias-sk) — exact lifecycle commands.
- **Look up:** [Skills configuration](../reference/configuration/skills-and-bindings.md#skills) — exposure and
  resolution settings.
