# How to author a repo-specific skill

Author a skill that lives in **this repo** under `.perk/skills/<name>/SKILL.md`, so its guidance
travels with the repo and is delivered into sessions like any installed skill. perk converges a
managed skills-CLI manifest fragment for these, so the only manual obligation is the
commit-push-resync cycle (the source resolves from your default branch).

**Prerequisite:** the repo is initialized via `perk init` (which runs `skills init`) and has a
GitHub origin. For the *judgment* of what makes a good skill, follow the `perk-skill-author` skill —
this how-to is the lifecycle, not the authoring craft.

## Steps

1. **Scaffold or create.** Either
   - `perk skills scaffold NAME` — writes the stub `.perk/skills/NAME/SKILL.md` and reconverges the
     fragment (a non-fatal "not committed — commit it" warning is expected for the fresh skill), or
   - `perk skills create NAME` — scaffolds **and** launches a write-capable authoring session
     following the `perk-skill-author` skill.

   Both are **create-only**: they refuse if `.perk/skills/NAME/` already exists and point you at
   `perk skills refine NAME` to re-open it.

2. **Author the `SKILL.md`.** Follow the `perk-skill-author` skill for the judgment — a concrete
   `description` (the WHEN-to-use triggers), scripts/references over prose, and self-contained
   delivery. The frontmatter rules are firm: `name` must equal the directory name, and
   `description` must be non-empty.

3. **Commit + push to the default branch**, then **re-run `perk init`** (or `perk doctor --fix`).
   The managed fragment resolves the skill from your repo's **default branch**, so an uncommitted
   or unpushed skill is not yet deliverable.

4. **`perk skills sync`** to materialize the link at `.agents/skills/NAME/SKILL.md`. A freshly
   inited repo may legitimately lack the link until this first sync.

5. **Refine later** with `perk skills refine NAME` — re-opens the existing skill in a write-capable
   session and **skips sync** (the file already exists; there is no `--from` input in v1).

6. **Delete** with `perk skills delete NAME --yes` when the skill is no longer wanted; it removes
   `.perk/skills/NAME/` and reconverges the fragment.

## See also

- [How to attach your own skill to a stage or command](./attach-a-skill-to-a-stage.md) — once a
  repo-authored skill is committed + synced (so it lands under `.agents/skills/<name>/`), bind it to
  a stage or command exactly like any installed skill.
- [`perk skills`](../reference/cli.md#perk-skills-alias-sk) — the full command reference for the
  authoring verbs and the upstream pass-throughs.
- [Configuration reference — Repo-authored skills](../reference/configuration.md#repo-authored-skills-piskills) —
  the convergence + commit-push-resync model behind these commands.

---

← Back to the [how-to router](index.md).
