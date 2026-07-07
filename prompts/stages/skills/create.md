You are running perk skills create — authoring a NEW repo-specific skill. Follow the `perk-skill-author` skill (read `.agents/skills/perk-skill-author/SKILL.md`).

  1. The skill directory `{{ repo_skills_rel }}/{{ skill_name }}/` has already been scaffolded with a TODO `SKILL.md` at `{{ skill_path }}`. Open it and replace the scaffold.
  2. Author the skill: write a concrete, trigger-phrase `description` (the entire discovery surface — name the tasks/phrases, not a vague topic), keep `SKILL.md` lean and self-contained (heavy/reference material goes in sibling `references/`/`scripts/` files the delivery symlink carries for free), and validate the frontmatter (`name` must equal the directory segment `{{ skill_name }}`; `description` non-empty).
  3. Stay within the soft scope: `{{ repo_skills_rel }}/{{ skill_name }}/**` plus any directly-required docs/bindings (add a binding only if the skill must fire at a stage/command — reconcile the docs in the same change). Do NOT touch unrelated files.

  Author the skill, then STOP — leave committing to the user. NEVER delegate the judgment, authoring, or the commit decision.

  Skill: {{ repo_skills_rel }}/{{ skill_name }}/SKILL.md