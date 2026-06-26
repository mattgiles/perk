# Repo-authored skills

Design record for perk's repo-authored skill source — the skills a repo writes for *itself*, which
perk renders into a second skills-CLI manifest fragment and the skills CLI then delivers to
sessions.

## Original design (source under `.pi/skills/`)

The feature was first built with the repo-authored skill **source** rooted at
`.pi/skills/<name>/SKILL.md`:

- **The path seam.** `perk/substrate/paths.py` is the sole construction site —
  `REPO_SKILLS_REL` (the forward-slash display string) and `repo_skills_dir(root)` (the `Path`).
  Every consumer (scaffold/create/refine/delete commands, frontmatter validation, the
  duplicate-skill exclusion) derives from one of these two symbols.
- **Install/runtime stays `.agents/`-anchored.** The skills-CLI install state (`.agents/skills/`)
  and the perk-managed manifest fragment (`.agents/manifest.d/perk-repo-skills.yaml`) are
  unaffected by where the *source* lives. The fragment encodes the self-referential GitHub source
  (repo URL + ref) and the skill names — it carries **no source subdirectory path**.
- **First-appearance remediation.** A freshly-declared skill is unresolvable until committed +
  pushed to the repo's default branch; the skills-sync failure message carries that remediation.

## Outcomes

**Superseded: source location moved from `.pi/skills/` to `.perk/skills/`** (Objective #878,
Node 4.1, `move-repo-skills`).

The `.pi/` dot-dir is not generally perk-owned (it is shared with Pi-native state), so anchoring
repo-authored skill *source* there was an ownership mistake. Objective #878 migrates each
perk-owned dot-path family to a dedicated `.perk/` root; the repo-skills source moved before the
feature hardened around the wrong path. What actually changed:

- **The seam** (`perk/substrate/paths.py`): `REPO_SKILLS_REL = ".perk/skills"` and
  `repo_skills_dir(root) -> root / ".perk" / "skills"`. Every consumer moved with it (single edit) —
  no consumer logic changed.
- **The manifest fragment is byte-identical.** It encodes no source subdirectory, so the move
  produces the same fragment content; "regeneration" is satisfied by the verify-gated reconverge
  re-reading the new location.
- **A forward-only `doctor --fix` migration** (`_migrate_legacy_repo_skills` in
  `perk/convergence/doctor/fixes.py`) relocates any legacy `.pi/skills/<name>` skill: moved when
  the `.perk/skills/<name>` target is absent, the redundant legacy copy dropped when byte-identical,
  and left in place with a reported conflict when the target differs. Filesystem-only, idempotent.
- **Remediation + display strings** now say `.perk/skills/`; the path-construction guard
  (`tests/test_paths_guard.py`) was generalized to guard both `.pi` and `.perk` dot-dirs so the
  family stays guarded at its new home.

Install/runtime stays under `.agents/` — only the *source* location moved.

**Deferred:** the factual `.pi/skills` path mentions in `docs/learned/workflow/init-external-cli.md`
and `write-capable-cold-doors.md` are refreshed by the Node 5.1 docs-reconciliation sweep, not here.
