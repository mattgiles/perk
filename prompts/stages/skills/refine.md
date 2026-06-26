You are running perk skills refine — improving an EXISTING repo-specific skill. Follow the perk-skill-author skill.

  1. Read the existing `SKILL.md` at `{{ skill_path }}` and the relevant repo context.
  2. Improve it in place: sharpen the `description` triggers (the entire discovery surface — name the tasks/phrases, not a vague topic), tighten/restructure the body, move heavy/reference material into sibling `references/`/`scripts/` files (the delivery symlink carries them for free), and re-validate the frontmatter (`name` must equal the directory segment `{{ skill_name }}`; `description` non-empty).
  3. Stay within the soft scope: `{{ repo_skills_rel }}/{{ skill_name }}/**` plus any directly-required docs/bindings (add a binding only if the skill must fire at a stage/command — reconcile the docs in the same change). Do NOT touch unrelated files.

  Improve the skill, then STOP — leave committing to the user. NEVER delegate the judgment, authoring, or the commit decision.

  Skill: {{ repo_skills_rel }}/{{ skill_name }}/SKILL.md