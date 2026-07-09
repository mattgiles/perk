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

   `create` also accepts **`--from <file|url>`** to seed authoring from a source document: a local
   file is read as seed DATA; an http(s) URL to a `SKILL.md` is fetched **in-session** (along with
   any sibling `references/`/`scripts/` files), treated as DATA, and ported selectively into the new
   skill. It always creates a fresh skill (no adoption) and the door stays offline.

   Both are **create-only**: they refuse if `.perk/skills/NAME/` already exists and point you at
   `perk skills refine NAME` to re-open it.

2. **Author the `SKILL.md`.** Follow the `perk-skill-author` skill for the judgment — a concrete
   `description` (the WHEN-to-use triggers), scripts/references over prose, and self-contained
   delivery. The frontmatter rules are firm: `name` must equal the directory name, and
   `description` must be non-empty.

   **Declare `stages:` deliberately.** The stub arrives with `stages: all` and a TODO — narrow it
   to the stage launches where the skill belongs: a stage-id list (e.g. `stages: [plan,
   implement]`), `all` (every stage launch), or `[]` (interactive-only — hidden from every cold
   stage launch). Skills bound via `[[bindings]]` are always exposed at their trigger regardless.
   `perk doctor` warns on a repo-authored skill that leaves `stages:` undeclared (exposed
   everywhere) or lists an unknown stage id. See
   [`[skills]` in the configuration reference](../reference/configuration.md#skills).

3. **Commit + push to the default branch**, then **re-run `perk init`** (or `perk doctor --fix`).
   The managed fragment resolves the skill from your repo's **default branch**, so an uncommitted
   or unpushed skill is not yet deliverable.

4. **`perk skills sync`** to materialize the link at `.agents/skills/NAME/SKILL.md`. A freshly
   inited repo may legitimately lack the link until this first sync.

5. **Refine later** with `perk skills refine NAME` — re-opens the existing skill in a write-capable
   session and **skips sync** (the file already exists). `refine` takes no `--from` — seeding from a
   source document is a `create`-only input.

6. **Delete** with `perk skills delete NAME --yes` when the skill is no longer wanted; it removes
   `.perk/skills/NAME/` and reconverges the fragment.

## Scoping a door-specific skill (hide it from the ambient prompt)

A skill that only matters inside one stage or command doesn't need to sit in every session's
system prompt. Add `disable-model-invocation: true` to its frontmatter and attach it via a
`[[bindings]]` row: pi then drops it from the ambient skill listing, while the delivered `nudge`
pointer carries the read path (``read `.agents/skills/<name>/SKILL.md` ``), so hiding never strands
it — the file stays on disk and `/skill:<name>` keeps working. perk's own workflow `perk-*` skills
use exactly this recipe. The extra frontmatter key is tolerated by perk's skill validation (`name`
and `description` remain the only required fields).

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
